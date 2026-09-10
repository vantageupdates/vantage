// Inventory-only decorative frame. No changes to native class animation artwork.
using System;
using System.IO;
public static class VantageClassFrame {
    public static void Render(string destination) {
        if(Path.GetFileName(destination)!="VantageClassFrame.tga")
            throw new ArgumentException("Expected dedicated class frame atlas.");
        using(var output=new BinaryWriter(File.Create(destination))) {
            var header=new byte[18];header[2]=2;header[12]=128;header[15]=1;
            header[16]=32;header[17]=40;output.Write(header);
            for(int y=0;y<256;y++)for(int x=0;x<128;x++) {
                double alpha=0;
                int px=x-2,py=y-2;
                if(px>=0&&px<78&&py>=0&&py<142) {
                    // Rounded signed-distance contour with a neutral, soft falloff.
                    double qx=Math.Abs(px+.5-39)-30,qy=Math.Abs(py+.5-71)-62;
                    double d=Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
                        +Math.Min(Math.Max(qx,qy),0)-6;
                    double cornerFade=.35+.65*(1-Math.Min(1,Math.Abs(px-38.5)/30)*Math.Min(1,Math.Abs(py-70.5)/62));
                    alpha=(38*Math.Exp(-d*d/.48)+10*Math.Exp(-d*d/5))*cornerFade;
                }
                byte a=(byte)Math.Round(alpha);
                output.Write((byte)(a>0?255:0));output.Write((byte)(a>0?255:0));
                output.Write((byte)(a>0?255:0));output.Write(a);
            }
        }
    }
}
