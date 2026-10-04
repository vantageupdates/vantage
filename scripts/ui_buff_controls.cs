// Native-size buff holders and transparent button chrome, never spell icons.
using System;
using System.IO;

public static class VantageBuffControls {
    static double Distance(double x,double y,double inset) {
        double radius=3-inset;
        double qx=Math.Abs(x-12)-(12-inset-radius);
        double qy=Math.Abs(y-12)-(12-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static double Coverage(int x,int y,double inset) {
        int count=0;
        for(int sy=0;sy<8;sy++)for(int sx=0;sx<8;sx++)
            if(Distance(x+(sx+.5)/8,y+(sy+.5)/8,inset)<=0)count++;
        return count/64.0;
    }
    static void Pixel(byte[] data,int x,int y,int r,int g,int b,int a) {
        int i=18+4*(y*64+x);
        data[i]=(byte)(a==0?0:b);data[i+1]=(byte)(a==0?0:g);
        data[i+2]=(byte)(a==0?0:r);data[i+3]=(byte)a;
    }
    public static void Patch(string destination) {
        if(Path.GetFileName(destination)!="Buff_Background.tga")
            throw new ArgumentException("Only the native buff background atlas is supported.");
        byte[] data=File.ReadAllBytes(destination);
        if(data.Length!=18+64*128*4 || data[0]!=0 || data[1]!=0 || data[2]!=2
            || data[12]!=64 || data[13]!=0 || data[14]!=128 || data[15]!=0
            || data[16]!=32 || data[17]!=40)
            throw new ArgumentException("Expected a top-origin 64x128 BGRA atlas.");
        // The existing long/short/single frames share the same five holders.
        // Preserve every byte outside x1..24,y1..124 and the five button cells.
        for(int y=0;y<124;y++)for(int x=0;x<24;x++) {
            int localY=y%25;
            if(localY==24) { Pixel(data,1+x,1+y,0,0,0,0);continue; }
            double a=Coverage(x,localY,.25);
            double edge=a==0?0:(a-Coverage(x,localY,1.25))/a;
            double face=21-7*(localY+.5)/24;
            int r=(int)Math.Round(face*(1-edge)+101*edge);
            int g=(int)Math.Round(face*(1-edge)+93*edge);
            int b=(int)Math.Round(face*(1-edge)+75*edge);
            Pixel(data,1+x,1+y,r,g,b,(int)Math.Round(a*255));
        }
        // The client can paint hover chrome in the name lane independently of
        // the icon decal. Keep ALL states clear, not just Normal/Disabled;
        // native BuffIcons, tooltips and cancellation bindings are untouched.
        for(int state=0;state<5;state++)for(int y=0;y<24;y++)for(int x=0;x<24;x++) {
            Pixel(data,32+x,24*state+y,0,0,0,0);
        }
        File.WriteAllBytes(destination,data);
    }
}
