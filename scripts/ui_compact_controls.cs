// Exact-size native footer faces; shared game artwork remains untouched.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

public static class VantageCompactControls {
    // Inventory123x20, Bank61x20, Combine60x20, Done/Social50x20.
    public static readonly int[,] Cells={{2,2,123,20},{130,2,61,20},
        {2,128,60,20},{67,128,50,20}};
    static double Distance(double x,double y,int w,int h,double inset) {
        double radius=4-inset;
        double qx=Math.Abs(x-w/2.0)-(w/2.0-inset-radius);
        double qy=Math.Abs(y-h/2.0)-(h/2.0-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static double Coverage(int x,int y,int w,int h,double inset) {
        int count=0;
        for(int sy=0;sy<8;sy++)for(int sx=0;sx<8;sx++)
            if(Distance(x+(sx+.5)/8,y+(sy+.5)/8,w,h,inset)<=0)count++;
        return count/64.0;
    }
    public static void Render(string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageCompactControls.tga")
            throw new ArgumentException("Only the compact native control atlas is supported.");
        using(var atlas=new Bitmap(256,256,PixelFormat.Format32bppArgb)) {
            // Normal, flyby, pressed, pressed-flyby, disabled.
            for(int cell=0;cell<Cells.GetLength(0);cell++)
            for(int state=0;state<5;state++)
            for(int y=0;y<20;y++)for(int x=0;x<Cells[cell,2];x++) {
                int w=Cells[cell,2];
                double a=Coverage(x,y,w,20,.25);if(a==0)continue;
                double edge=(a-Coverage(x,y,w,20,1))/a,t=(y+.5)/20;
                bool down=state==2||state==3,hover=state==1||state==3;
                double face=down?18+11*t:32-14*t+3*Math.Exp(-Math.Pow((t-.2)/.18,2));
                if(hover)face+=7;
                if(state==4)face=18-3*t;
                double rim=edge*(state==4?.12:hover?.38:down?.28:.23);
                int tone=(int)Math.Round(face*(1-rim)+255*rim);
                atlas.SetPixel(Cells[cell,0]+x,Cells[cell,1]+23*state+y,
                    Color.FromArgb((int)Math.Round(a*255),tone,tone,tone));
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                var header=new byte[18];header[2]=2;header[13]=1;header[15]=1;
                header[16]=32;header[17]=40;output.Write(header);
                for(int y=0;y<256;y++)for(int x=0;x<256;x++) {
                    var c=atlas.GetPixel(x,y);output.Write(c.B);output.Write(c.G);output.Write(c.R);output.Write(c.A);
                }
            }
            if(!String.IsNullOrEmpty(preview))atlas.Save(preview,ImageFormat.Png);
        }
    }
}
